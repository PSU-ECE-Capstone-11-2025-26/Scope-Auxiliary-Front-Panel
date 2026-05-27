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
    private About _aboutView;
    
    private readonly Dictionary<string, ScopeInstance> _scopes = new();

    public override void _Ready()
    {
	    Global.Instance.Toast = GetNode<Control>("Toast");
	    Global.Instance.LoadConfig();

	    _homeView = GetNode<Home>("ViewManager/Home");
	    _scopesView = GetNode<Scopes>("ViewManager/Scopes");
	    _macroView = GetNode<Macros>("ViewManager/Macros");
	    _aboutView = GetNode<About>("ViewManager/About");
	    _aboutView.SetFromConfig(Global.Instance.Config);
	    _scopesView.ScopeToggled += ToggleScope;

	    WebSocketClient.Instance.Connect(WebSocketClient.SignalName.Connected, Callable.From(OnSocketFirstConnect),
		    (uint)ConnectFlags.OneShot);
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
			    case HandshakePacketData hs:
				    Global.Logger.Log(LogLevel.Debug, $"Handshaked with {hs.Id} {hs.Version}");
				    GetNode<About>("ViewManager/About").AddGeneralInfo("tekafp version", hs.Version);
				    break;
			    case ScopeListPacketData sl:
			    {
				    Global.Logger.Log(LogLevel.Debug, $"Received ScopeList count={sl.Scopes.Count}");
				    _scopesView.ClearScopes();
				    foreach (KeyValuePair<string, bool> entry in sl.Scopes)
				    {
					    _scopesView.AddScope(entry.Key, entry.Value);
				    }

				    _scopesView.SetSearchComplete();
				    break;
			    }
			    case ScopeInfoPacketData si:
				    _homeView.UpdateScope(si.ResourceName, si.Idn, si.ChannelCount);
				    Global.Instance.Config.LastUsedScopes[0] = si.ResourceName;
				    Global.Instance.SaveConfig(true);
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
			    case ErrorPacketData ep:
				    if (ep.ErrorCode == 0)
				    {
					    _scopes.Remove(ep.ResourceName);
					    _homeView.RemoveScope(ep.ResourceName);
				    }
				    Global.Logger.Log(LogLevel.Error, ep.ErrorStr, true);
				    break;
		    }
	    }
    }

    private void OnSocketFirstConnect()
    {
	    switch (Global.Instance.Config.AutoConnect)
	    {
		    case AutoConnectMode.LastUsed:
			    // TODO: update for reconnecting to multiple scopes
			    if (Global.Instance.Config.LastUsedScopes.Count > 0)
			    {
				    string rn = Global.Instance.Config.LastUsedScopes[0];
				    ToggleScope(rn, true);
				    Global.Logger.Log(LogLevel.Info, $"Connecting to last scope [{rn}]", true);
			    }
			    break;
		    case AutoConnectMode.FirstAvailable:
			    _scopesView.Connect(Scopes.SignalName.SearchComplete,
				    Callable.From(OnFirstScopeSearch), (uint)ConnectFlags.OneShot);
			    _scopesView.RefreshList();
			    break;
		    case AutoConnectMode.None:
			    break;
	    }
    }

    private void OnFirstScopeSearch()
    {
	    if (_scopesView.List.GetChildCount() > 0)
	    {
		    ToggleScope(_scopesView.List.GetChild<ScopeOption>(0).ResourceName, true);
	    }
    }

    private void ToggleScope(string resourceName, bool state)
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
