using AFP.Components;
using AFP.Core;
using AFP.Packet;
using AFP.Packet.Data;
using Godot;

namespace AFP.View;

public partial class Scopes : VBoxContainer
{
	[Signal]
	public delegate void ScopeToggledEventHandler(string resourceName, bool enabled);
	[Signal]
	public delegate void SearchCompleteEventHandler();

	[Export] private PackedScene _scopeOptionScene;
	public VBoxContainer List;
	private ButtonGroup _group;
	private bool _refresh;

	public override void _Ready()
    {
	    List = GetNode<VBoxContainer>("%ScopesList");
	    _group = new ButtonGroup();
	    _group.AllowUnpress = true;
	    GetNode<Button>("HBoxContainer/RefreshButton").Pressed += RefreshList;
	    VisibilityChanged += OnVisibilityChanged;
    }

	private void OnVisibilityChanged()
	{
		if (Visible) RefreshList();
	}

	public void RefreshList()
	{
		if (_refresh)
		{
			GD.Print("skip refresh");
			return;
		}
		_refresh = true;
		GetNode<Button>("HBoxContainer/RefreshButton").Text = "Searching...";
	    WebSocketClient.Instance.SendPacket(new PacketContainer
	    {
		    Origin = "client",
		    Data =
		    [
			    new ScopeActionPacketData
			    {
				    Action = "list",
				    ResourceName = null
			    }
		    ]
	    });
    }

	public void SetSearchComplete()
	{
		_refresh = false;
		GetNode<Button>("HBoxContainer/RefreshButton").Text = "Refresh";
		EmitSignal(SignalName.SearchComplete);
	}

    public void AddScope(string resourceName, bool enabled)
    {
	    var s = _scopeOptionScene.Instantiate<ScopeOption>();
	    s.Init(resourceName, enabled, _group);
	    s.ScopeToggled += _onScopeToggled;
	    List.AddChild(s);
    }

    public void ClearScopes()
    {
	    foreach (Node node in List.GetChildren())
	    {
		    var child = (ScopeOption)node;
		    child.ScopeToggled -= _onScopeToggled;
		    child.QueueFree();
	    }
    }

    private void _onScopeToggled(bool enabled, string resourceName)
    {
	    Global.Logger.Log(LogLevel.Debug, $"Scope toggle {resourceName} {enabled}");
	    EmitSignal(SignalName.ScopeToggled, resourceName, enabled);
    }
}
