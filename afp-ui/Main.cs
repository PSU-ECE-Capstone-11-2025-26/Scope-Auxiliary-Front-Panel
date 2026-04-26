using System.Collections.Generic;
using AFP.Components;
using AFP.Packet;
using AFP.Packet.Data;
using AFP.View;
using Godot;

namespace AFP;

public partial class Main : Control
{
    // specs from https://4dsystems.com.au/products/gen4-4dpi-70ct-clb/
    private const float DisplaySize = 7.0f;
    private const int DisplayWidth = 800;
    private const int DisplayHeight = 480;

    private Home _homeView;
    private Scopes _scopesView;
    private Macros _macroView;

    public override void _Ready()
    {
        if (OS.HasFeature("debug"))
        {
            SetDevWindowSize();
        }

        Global.Instance.Toast = GetNode<Control>("Toast");
        Global.Instance.LoadConfig();
        
        GetNode<TabContainer>("ViewManager").SetTabHidden(2, true);
        _homeView = GetNode<Home>("ViewManager/Home");
        _scopesView = GetNode<Scopes>("ViewManager/Scopes");
        _macroView = GetNode<Macros>("ViewManager/Macros");
        _scopesView.ScopeToggled += _onScopeToggled;
        
        WsClient.Instance.Connect(Global.Instance.Config.WebSocketUrl);
    }

    public override void _Process(double delta)
    {
	    ProcessPackets();
    }

    private void ProcessPackets()
    {
	    var client = WsClient.Instance;
	    if (client.ReceiveQueue.Count == 0) return;
	    PacketContainer pc = client.ReceiveQueue.Dequeue();
	    foreach (IPacketData pd in pc.Data)
	    {
		    switch (pd)
		    {
			    case ScopeListPacketData sl:
			    {
				    Global.Instance.Log(3, $"Received ScopeList count={sl.Scopes.Count}");
				    foreach (KeyValuePair<string, bool> entry in sl.Scopes)
				    {
					    _scopesView.AddScope(entry.Key, entry.Value);
				    }

				    break;
			    }
			    case ScopeInfoPacketData si:
				    _homeView.UpdateScope(si.ResourceName, si.Idn, si.ChannelCount);
				    Global.Instance.Log(0, $"Scope Connected {si.ResourceName}", true);
				    Global.Instance.Log(3, $"scope specs: ChannelCount={si.ChannelCount}");
				    break;
			    case MacroStatePacketData ms:
				    for (ushort i = 0; i < ms.Macros.Length; i++)
				    {
					    _macroView.GetMacro(i)
						    .SetState(ms.Macros[i] ? MacroControl.State.Saved : MacroControl.State.Empty);
				    }

				    break;
		    }
	    }
    }

    private void _onScopeToggled(string resourceName, bool state)
    {
	    if (state)
	    {
		    _homeView.AddScope(resourceName);
	    }
	    else
	    {
		    _homeView.RemoveScope(resourceName);
	    }
    }

    private void SetDevWindowSize()
    {
        int dpi = DisplayServer.ScreenGetDpi();
        Vector2I newSize = CalcDevWindowSize(dpi);
        GetWindow().Size = newSize;
        GetWindow().ContentScaleSize = newSize;
    }

    private static Vector2I CalcDevWindowSize(int dpi)
    {
        const float aspectRatio = (float)DisplayWidth / DisplayHeight;
        float hInch = DisplaySize / (float.Sqrt(float.Pow(aspectRatio, 2) + 1));
        float wInch = aspectRatio * hInch;
        
        int hPixels = Mathf.RoundToInt(hInch * dpi);
        int wPixels = Mathf.RoundToInt(wInch * dpi);
        
        return new Vector2I(wPixels, hPixels);
    }
}
