using System.Collections.Generic;
using AFP.Core;
using AFP.Resources;
using Godot;

namespace AFP.View;

public partial class About : MarginContainer
{
	[Export] private Button _forceCloseButton;
	[Export] private Tree _aboutTree;
	[Export] private CheckButton _debugToggle;
	[Export] private Button _setDevWinSize;
	[Export] private OptionButton _autoConnect;
	[Export] private SoftwareCredit[] _softwareCredits;

	private TreeItem _aboutTreeRoot;
	private VBoxContainer _licenseList;

	// specs from https://4dsystems.com.au/products/gen4-4dpi-70ct-clb/
	private const float DisplaySize = 7.0f;
	private const int DisplayWidth = 800;
	private const int DisplayHeight = 480;

	public override void _Ready()
	{
		_forceCloseButton.Pressed += () => GetTree().Quit(0);
		_aboutTreeRoot = _aboutTree.CreateItem();
		AddGeneralInfo("Device Hostname", System.Net.Dns.GetHostName());
		AddGeneralInfo("afp-ui version", ProjectSettings.GetSetting("application/config/version").ToString());
		_debugToggle.Toggled += _onDebugToggled;
		_autoConnect.ItemSelected += OnItemSelected;
		if (OS.HasFeature("debug"))
		{
			_setDevWinSize.Show();
			_setDevWinSize.Pressed += SetDevWindowSize;
		}

		_licenseList = GetNode<VBoxContainer>("%LicenseList");
		{
			using FileAccess afpLicense =
				FileAccess.Open("res://licenses/raw/afp.LICENSE.txt", FileAccess.ModeFlags.Read);
			AddLicense("Auxiliary Front Panel", afpLicense.GetAsText());
		}
		AddLicense("Godot Engine", Engine.GetLicenseText());
		foreach (SoftwareCredit softwareCredit in _softwareCredits)
		{
			FileAccess licenseFile = FileAccess.Open(softwareCredit.LicenseFile, FileAccess.ModeFlags.Read);
			AddLicense(softwareCredit.SoftwareName, licenseFile.GetAsText());
			licenseFile.Close();
		}
	}

	public void AddGeneralInfo(string key, string value)
	{
		TreeItem newItem = _aboutTreeRoot.CreateChild();
		newItem.SetSelectable(0, false);
		newItem.SetSelectable(1, false);
		newItem.SetText(0, key);
		newItem.SetText(1, value);
	}

	private void AddLicense(string title, string licenseText)
	{
		var item = new FoldableContainer();
		item.Folded = true;
		item.Title = title;
		var label = new Label();
		label.Text = licenseText;
		item.AddChild(label);
		_licenseList.AddChild(item);
	}

	public void SetFromConfig(Config cfg)
	{
		_debugToggle.ButtonPressed = cfg.DebugMode;
		_autoConnect.Selected = (int)cfg.AutoConnect;
	}

	private static void _onDebugToggled(bool enabled)
	{
		Global.Instance.Config.DebugMode = enabled;
		Global.Logger.Log(LogLevel.Debug, "debug enabled", true);
	}

	private static void OnItemSelected(long item)
	{
		Global.Instance.Config.AutoConnect = (AutoConnectMode)item;
		Global.Instance.SaveConfig();
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
