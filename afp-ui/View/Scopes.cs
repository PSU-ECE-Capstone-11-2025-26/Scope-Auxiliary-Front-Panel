using AFP.Components;
using AFP.Packet;
using AFP.Packet.Data;
using Godot;

namespace AFP.View;

public partial class Scopes : VBoxContainer
{
	[Export]
	private PackedScene _scopeOptionScene;
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
	    WsClient.Instance.SendPacket(new PacketContainer
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
	    s.ScopeToggled += _on_scope_toggled;
	    _list.AddChild(s);
    }

    private void ClearScopes()
    {
	    foreach (Node node in _list.GetChildren())
	    {
		    var child = (ScopeOption)node;
		    child.ScopeToggled -= _on_scope_toggled;
		    child.QueueFree();
	    }
    }

    private void _on_scope_toggled(bool enabled, string resourceName)
    {
	    Global.Instance.Log(3, $"Scope toggle {resourceName} {enabled}");
	    WsClient.Instance.QueuePacketData(new ScopeActionPacketData
		    {
			    Action = enabled ? "enable" : "disable",
			    ResourceName = resourceName
		    });
    }
}
