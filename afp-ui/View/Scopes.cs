using Godot;

namespace AFP.View;

public partial class Scopes : ScrollContainer
{
    private TreeItem _root;
    private Tree _tree;

    public override void _Ready()
    {
        _tree = GetNode<Tree>("VBoxContainer/Tree");
        _root = _tree.CreateItem();
        _tree.HideRoot = true;
        _tree.SetColumnTitle(0,  "EN");
        _tree.SetColumnTitle(1, "IDN");
        _tree.ColumnTitlesVisible = true;
        _tree.SetColumnCustomMinimumWidth(0, 20);
        _tree.SetColumnExpand(0, false);
        _tree.SetColumnExpand(1, true);

        for (var i = 0; i < 5; i++)
        {
            AddScope(false, "USB0::0x0699::0x0363::C102912::INSTR");
            AddScope(false, "TCPIP::192.168.0.1::INSTR");
        }
    }

    private void AddScope(bool enabled, string idn)
    {
        TreeItem sc = _tree.CreateItem(_root);
        sc.SetCellMode(0, TreeItem.TreeCellMode.Check);
        sc.SetChecked(0, enabled);
        sc.SetEditable(0, true);
        sc.SetSelectable(1, false);
        sc.SetText(1, idn);
    }
}