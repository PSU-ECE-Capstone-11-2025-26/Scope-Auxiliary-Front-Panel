using AFP.Components;
using Godot;

namespace AFP.View;

struct Scope(string idn, bool enabled)
{
	private string _idn = idn;
	private bool _enabled = enabled;
}

public partial class Scopes : ScrollContainer
{
	[Export]
	private PackedScene _scopeOptionScene;
	private VBoxContainer _list;
	private ButtonGroup _group;

    public override void _Ready()
    {
	    _list = GetNode<VBoxContainer>("ScopesList");
	    _group = new ButtonGroup();
	    _group.AllowUnpress = true;
        for (var i = 0; i < 5; i++)
        {
            AddScope("USB0::0x0699::0x0363::C102912::INSTR", true);
            AddScope("TCPIP::192.168.0.1::INSTR", false);
        }
    }

    private void AddScope(string idn, bool enabled)
    {
	    var s = _scopeOptionScene.Instantiate<ScopeOption>();
	    s.Init(idn, enabled, _group);
	    _list.AddChild(s);
    }
}
