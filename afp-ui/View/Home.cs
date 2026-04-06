using Godot;

namespace AFP.View;
public partial class Home : VBoxContainer
{
	public override void _Ready()
	{
		var _tree = GetNode<Tree>("Tree");
		TreeItem _root = _tree.CreateItem();
		_root.SetText(0, "USB0::0x0699::0x0363::C102912::INSTR");
		_root.SetExpandRight(0, true);
		var n =  _root.CreateChild();
		n.SetText(0, "Status");
		n.SetText(1, "CONNECTED");
		n = _root.CreateChild();
		n.SetText(0, "Available Channels");
		n.SetText(1, "8");
	}
}
