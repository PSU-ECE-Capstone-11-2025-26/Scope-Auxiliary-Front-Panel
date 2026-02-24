using Godot;

namespace AFP.Resources;

[GlobalClass]
public partial class TabConfig : Resource
{

    [Export] public Texture2D Icon { get; set; }
    [Export] public int MaxIconWidth { get; set; } = 25;
}