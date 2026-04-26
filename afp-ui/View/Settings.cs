using Godot;

namespace AFP.View;

public partial class Settings : MarginContainer
{
	public override void _Ready()
	{
		GetNode<Button>("VBox/ExitButton").Pressed += () => GetTree().Quit(0);
		GetNode<Label>("CreditsPopup/VBoxContainer/VersionLabel").Text =
			$"AFP-UI v{ProjectSettings.GetSetting("application/config/version")}";
		GetNode<CheckButton>("VBox/AdvancedContainer/VBoxContainer/DebugMode").Toggled += _onDebugToggled;
		GetNode<Button>("VBox/AdvancedContainer/VBoxContainer/ForceReconnect").Pressed += _onReconnectButtonPressed;
	}

	private void _onReconnectButtonPressed()
	{
		bool success = WsClient.Instance.Reconnect();
		Global.Instance.Log(3, $"Reconnect successful: {success}", true);
	}

	private void _onDebugToggled(bool enabled)
	{
		Global.Instance.Config.DebugMode = enabled;
		Global.Instance.Log(3, "debug enabled", true);
		GetNode<Button>("VBox/AdvancedContainer/VBoxContainer/ForceReconnect").SetVisible(enabled);
	}
}
