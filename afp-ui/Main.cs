using System.Collections.Generic;
using AFP.Components;
using AFP.Core;
using AFP.Packet;
using AFP.Packet.Data;
using AFP.Resources;
using AFP.View;
using Godot;

namespace AFP;

public partial class Main : Control
{
    private Home _homeView;
    private Scopes _scopesView;
    private Macros _macroView;
    
    private readonly Dictionary<string, ScopeInstance> _scopes = new();

    public override void _Ready()
    {
        Global.Instance.Toast = GetNode<Control>("Toast");
        Global.Instance.LoadConfig();
        
        _homeView = GetNode<Home>("ViewManager/Home");
        _scopesView = GetNode<Scopes>("ViewManager/Scopes");
        _macroView = GetNode<Macros>("ViewManager/Macros");
        _scopesView.ScopeToggled += _onScopeToggled;
        
        WebSocketClient.Instance.Connect(Global.Instance.Config.WebSocketUrl);
    }

    public override void _Process(double delta)
    {
	    ProcessPackets();
    }

    private void ProcessPackets()
    {
	    var client = WebSocketClient.Instance;
	    if (client.ReceiveQueue.Count == 0) return;
	    PacketContainer pc = client.ReceiveQueue.Dequeue();
	    foreach (IPacketData pd in pc.Data)
	    {
		    switch (pd)
		    {
			    case ScopeListPacketData sl:
			    {
				    Global.Logger.Log(LogLevel.Debug, $"Received ScopeList count={sl.Scopes.Count}");
				    _scopesView.SetSearchDone();
				    foreach (KeyValuePair<string, bool> entry in sl.Scopes)
				    {
					    _scopesView.AddScope(entry.Key, entry.Value);
				    }

				    break;
			    }
			    case ScopeInfoPacketData si:
				    _homeView.UpdateScope(si.ResourceName, si.Idn, si.ChannelCount);
				    ScopeInstance scope = _scopes[si.ResourceName];
				    scope.Idn = si.Idn;
				    scope.ChannelCount = si.ChannelCount;
				    scope.ConnectionState = ScopeConnectionState.Connected;
				    Global.Logger.Log(LogLevel.Info, $"Scope Connected {si.ResourceName}", true);
				    Global.Logger.Log(LogLevel.Debug, $"scope specs: ChannelCount={si.ChannelCount}");
				    break;
			    case MacroStatePacketData ms:
				    for (ushort i = 0; i < ms.Macros.Length; i++)
				    {
					    _macroView.GetMacro(i)
						    .SetState(ms.Macros[i] ? MacroControl.State.Saved : MacroControl.State.Empty);
				    }

				    break;
			    case LogMessagePacketData lm:
				    Global.Logger.Log((LogLevel)lm.Level, lm.Message, lm.Toast);
				    break;
		    }
	    }
    }

    private void _onScopeToggled(string resourceName, bool state)
    {
	    WebSocketClient.Instance.QueuePacketData(new ScopeActionPacketData
	    {
		    Action = state ? "enable" : "disable",
		    ResourceName = resourceName
	    });
	    if (state)
	    {
		    _scopes[resourceName] = new ScopeInstance(resourceName, null, ScopeConnectionState.Connecting, 0);
		    _homeView.AddScope(resourceName);
	    }
	    else
	    {
		    if (_scopes.Remove(resourceName))
		    {
			    _homeView.RemoveScope(resourceName);
		    }
		    else
		    {
			    Global.Logger.Log(LogLevel.Warning, $"Attempted to remove nonexistent scope {resourceName}");
		    }
	    }
    }
}
