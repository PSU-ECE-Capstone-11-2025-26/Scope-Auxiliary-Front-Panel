using AFP.Core;
using AFP.Packet.Data;
using Godot;

namespace AFP.View;

public partial class Macros : MarginContainer
{
	[Export] private Texture2D _macroIcon;
	[Export] private HBoxContainer _shortcutContainer;
	[Export] private Button _recordButton;
	[Export] public ushort ShortCutCount { get; set; } = 4;
	private Timer _timer;
	private bool _recording;
	private ushort _recordingSlot;

	public override void _Ready()
	{
		_timer = GetNode<Timer>("RecordTimer");
		_timer.Timeout += TimerOnTimeout;
		_recordButton.Pressed += SaveRecording;
		for (ushort i = 0; i < ShortCutCount; i++)
		{
			ushort id = i;
			var b = new MenuButton();
			b.Flat = false;
			b.Text = $"Macro {id + 1}";
			b.GetPopup().AddSeparator("Select an action");
			b.GetPopup().AddItem("Record", 0);
			b.GetPopup().AddItem("Delete", 1);
			b.GetPopup().IdPressed += (menuId) => ShortcutOnPressed(id, menuId);
			_shortcutContainer.AddChild(b);
		}
		UpdateMacros([true, false, false, false]);
	}

	private void TimerOnTimeout()
	{
		SaveRecording();
		Global.Logger.Log(LogLevel.Info, "Recording saved (30s timeout)", true);
	}

	/// <summary>
	/// Update the state of the macros.
	/// </summary>
	/// <param name="macros">An array of true/false indicating whether a slot is occupied.</param>
	public void UpdateMacros(bool[] macros)
	{
		for (ushort i = 0; i < macros.Length; i++)
		{
			var btn = _shortcutContainer.GetChild<MenuButton>(i);
			btn.GetPopup().SetItemDisabled(btn.GetPopup().GetItemIndex(1), !macros[i]);
			btn.Icon = macros[i] ? _macroIcon : null;
		}
	}

	/// <summary>
	/// Start a macro recording.
	/// </summary>
	/// <param name="id">The slot id to record to.</param>
	private void StartRecording(ushort id)
	{
		SetLock(true);
		_recording = true;
		_recordingSlot = id;
		WebSocketClient.Instance.QueuePacketData(new MacroActionPacketData
		{
			Action = MacroAction.Record,
			Slot = _recordingSlot,
		});
		_recordButton.Text = $"Stop recording Macro {_recordingSlot + 1}";
		_recordButton.Show();
		_timer.Start();
	}

	/// <summary>
	/// Save the active recording.
	/// </summary>
	private void SaveRecording()
	{
		if (!_recording) return;
		_timer.Stop();
		WebSocketClient.Instance.QueuePacketData(new MacroActionPacketData
		{
			Action = MacroAction.Save,
			Slot = _recordingSlot,
		});
		_recordButton.Hide();
		_recording = false;
		SetLock(false);
	}

	private static void DeleteRecording(ushort id)
	{
		WebSocketClient.Instance.QueuePacketData(new MacroActionPacketData
		{
			Action = MacroAction.Delete,
			Slot = id,
		});
	}

	private void SetLock(bool locked)
	{
		foreach (Node button in _shortcutContainer.GetChildren())
		{
			((MenuButton)button).Disabled = locked;
		}
	}

	private void ShortcutOnPressed(ushort id, long menuId)
	{
		switch (menuId)
		{
			case 0: // record
				if (_recording)
				{
					SaveRecording();
				}
				else
				{
					StartRecording(id);
				}

				break;
			case 1: // delete
				DeleteRecording(id);
				break;
		}
	}
}
