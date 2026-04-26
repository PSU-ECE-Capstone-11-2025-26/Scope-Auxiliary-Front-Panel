using System;
using AFP.Packet.Data;
using Godot;

namespace AFP.Components;

public partial class MacroControl : VBoxContainer
{
	public ushort Slot;
	private ColorRect _stateIndicator;
	private Label _stateLabel;
	private Button _recordButton;

	public enum State
	{
		Empty,
		Recording,
		Saved,
	}

	public override void _Ready()
	{
		_stateIndicator = GetNode<ColorRect>("StateColor");
		_stateLabel = GetNode<Label>("StateLabel");
		_recordButton = GetNode<Button>("RecordButton");
		_recordButton.Toggled += _onRecordButtonPressed;
		SetState(State.Empty);
	}

	private void _onRecordButtonPressed(bool pressed)
	{
		if (pressed)
		{
			SetState(State.Recording);
			WsClient.Instance.QueuePacketData(
				new MacroRecordPacketData
				{
					Record = true,
					Slot = Slot
				});
		}
		else
		{
			SetState(State.Saved);
			WsClient.Instance.QueuePacketData(
				new MacroRecordPacketData
				{
					Record = false,
					Slot = Slot
				});
		}
	}

	public void SetState(State state)
	{
		_stateLabel.Text = state.ToString();
		switch (state)
		{
			case State.Empty:
				_stateIndicator.Color = Colors.Green;
				_recordButton.Text = "Record";
				break;
			case State.Recording:
				_stateIndicator.Color = Colors.Firebrick;
				_recordButton.Text = "Save";
				break;
			case State.Saved:
				_stateIndicator.Color = Colors.Gold;
				_recordButton.Text = "Record";
				break;
			default:
				throw new ArgumentOutOfRangeException(nameof(state), state, "Invalid state");
		}
	}
}
