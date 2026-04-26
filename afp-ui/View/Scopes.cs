using AFP.Components;
using AFP.Packet;
using AFP.Packet.Data;
using Godot;

namespace AFP.View;

public partial class Scopes : VBoxContainer
{
	[Signal]
	public delegate void ScopeToggledEventHandler(string resourceName, bool enabled);

	[Export] private PackedScene _scopeOptionScene;
	private VBoxContainer _list;
	private ButtonGroup _group;

	public override void _Ready()
    {
	    _list = GetNode<VBoxContainer>("%ScopesList");
	    _group = new ButtonGroup();
	    _group.AllowUnpress = true;
	    GetNode<Button>("RefreshButton").Pressed += RefreshList;
    }

    private void RefreshList()
    {
	    Core.WsClient.Instance.SendPacket(new PacketContainer
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
	    ClearScopes();
    }

    public void AddScope(string resourceName, bool enabled)
    {
	    var s = _scopeOptionScene.Instantiate<ScopeOption>();
	    s.Init(resourceName, enabled, _group);
	    s.ScopeToggled += _onScopeToggled;
	    _list.AddChild(s);
    }

    private void ClearScopes()
    {
	    foreach (Node node in _list.GetChildren())
	    {
		    var child = (ScopeOption)node;
		    child.ScopeToggled -= _onScopeToggled;
		    child.QueueFree();
	    }
    }

    private void _onScopeToggled(bool enabled, string resourceName)
    {
	    Core.Global.Instance.Log(3, $"Scope toggle {resourceName} {enabled}");
	    EmitSignal(SignalName.ScopeToggled, resourceName, enabled);
    }
}
