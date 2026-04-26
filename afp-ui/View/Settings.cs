using AFP.Core;
using Godot;

namespace AFP.View;

public partial class Settings : MarginContainer
{
	public override void _Ready()
	{
		GetNode<Button>("ScrollContainer/VBox/ExitButton").Pressed += () => GetTree().Quit(0);
		GetNode<Label>("ScrollContainer/VBox/VBoxContainer/TabContainer/About").Text =
			$"AFP-UI v{ProjectSettings.GetSetting("application/config/version")}";
		GetNode<CheckButton>("ScrollContainer/VBox/AdvancedContainer/VBoxContainer/DebugMode").Toggled +=
			_onDebugToggled;
	}

	private static void _onDebugToggled(bool enabled)
	{
		Global.Instance.Config.DebugMode = enabled;
		Global.Logger.Log(LogLevel.Debug, "debug enabled", true);
	}
}
