using AFP.Core;
using Godot;

namespace AFP.View;

public partial class Settings : MarginContainer
{
	[Export] private Button _forceCloseButton;
	[Export] private Label _aboutLabel;
	[Export] private CheckButton _debugToggle;
	[Export] private Button _setDevWinSize;

	// specs from https://4dsystems.com.au/products/gen4-4dpi-70ct-clb/
	private const float DisplaySize = 7.0f;
	private const int DisplayWidth = 800;
	private const int DisplayHeight = 480;

	public override void _Ready()
	{
		_forceCloseButton.Pressed += () => GetTree().Quit(0);
		_aboutLabel.Text = $"AFP-UI v{ProjectSettings.GetSetting("application/config/version")}";
		_debugToggle.Toggled += _onDebugToggled;
		if (OS.HasFeature("debug"))
		{
			_setDevWinSize.Show();
			_setDevWinSize.Pressed += SetDevWindowSize;
		}
	}

	private static void _onDebugToggled(bool enabled)
	{
		Global.Instance.Config.DebugMode = enabled;
		Global.Logger.Log(LogLevel.Debug, "debug enabled", true);
	}

	private void SetDevWindowSize()
	{
		int dpi = DisplayServer.ScreenGetDpi();
		Vector2I newSize = CalcDevWindowSize(dpi);
		GetWindow().Size = newSize;
		GetWindow().ContentScaleSize = newSize;
	}

	private static Vector2I CalcDevWindowSize(int dpi)
	{
		const float aspectRatio = (float)DisplayWidth / DisplayHeight;
		float hInch = DisplaySize / (float.Sqrt(float.Pow(aspectRatio, 2) + 1));
		float wInch = aspectRatio * hInch;

		int hPixels = Mathf.RoundToInt(hInch * dpi);
		int wPixels = Mathf.RoundToInt(wInch * dpi);

		return new Vector2I(wPixels, hPixels);
	}
}
