
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
	
    private Scopes _scopesView;

    public override void _Ready()
    {
        if (OS.HasFeature("debug"))
        {
            SetDevWindowSize();
        }

        Global.Instance.Toast = GetNode<Control>("Toast");
        Global.Instance.LoadConfig();
        
        _scopesView = GetNode<Scopes>("ViewManager/Scopes");
        
        WsClient.Instance.Connect(Global.Instance.Config.WebSocketUrl);
    }

    public override void _Process(double delta)
    {
	    ProcessPackets();
    }

    public override void _Input(InputEvent @event)
    {
        if (@event.IsActionPressed("ui_accept"))
        {
            Global.Instance.Toast.Call("add_message_compat", 0, "this is a test info");
            Global.Instance.Toast.Call("add_message_compat", 1, "this is a test warning");
            Global.Instance.Toast.Call("add_message_compat", 2, "this is a test errorrrrrrrr");
        }
    }

    private void ProcessPackets()
    {
	    var client = WsClient.Instance;
	    if (client.PacketQueue.Count == 0) return;
	    PacketContainer pc = client.PacketQueue.Dequeue();
	    foreach (IPacketData pd in pc.Data)
	    {
		    if (pd is ScopeListPacketData sl)
		    {
			    foreach (string s in sl.Scopes) _scopesView.AddScope(s, false);
		    }
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
