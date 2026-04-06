using AFP.Resources;
using Godot;

namespace AFP.View;

public partial class ViewManager : TabContainer
{
    [Export] private TabConfig[] TabConfig { get; set; }

    public override void _Ready()
    {
        for (var i = 0; i < TabConfig.Length; i++)
        {
            SetTabIcon(i, TabConfig[i].Icon);
            SetTabIconMaxWidth(i, TabConfig[i].MaxIconWidth);
        }
    }
}