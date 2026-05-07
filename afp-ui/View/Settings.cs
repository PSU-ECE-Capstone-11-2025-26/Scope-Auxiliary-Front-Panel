using Godot;

namespace AFP.View;

public partial class Settings : MarginContainer
{
	public override void _Ready()
	{
		GetNode<Button>("VBox/Button2").Pressed += () => GetTree().Quit(0);
	}
}
