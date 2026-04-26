using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using AFP.Packet;
using AFP.Packet.Data;
using Godot;

namespace AFP.Core;

public partial class WebSocketClient : Node
{
	public static WebSocketClient Instance { get; private set; }

	public Queue<PacketContainer> ReceiveQueue { get; private set; }
	private readonly Queue<IPacketData> _sendQueue = new();

	private WebSocketPeer _socket;
	private WebSocketPeer.State _prevState = WebSocketPeer.State.Closed;

	private readonly JsonSerializerOptions _options = new JsonSerializerOptions
	{
		PropertyNameCaseInsensitive = true,
		PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
	};

	public override void _Ready()
	{
		Instance = this;
		ReceiveQueue = new Queue<PacketContainer>();
		SetProcess(false);
	}

	public override void _ExitTree()
	{
		if (_socket.GetReadyState() != WebSocketPeer.State.Closed)
		{
			_socket.Close(reason: "application exiting");
		}
	}

	public bool Connect(string url)
	{
		_socket = new WebSocketPeer();
		Error err = _socket.ConnectToUrl(url);
		if (err == Error.Ok)
		{
			GD.Print($"WebSocket: connecting to {url}...");
			SetProcess(true);
			return true;
		}
		else
		{
			GD.PushError("WebSocket: couldn't connect (params or peer invalid?)");
			SetProcess(false);
			return false;
		}
	}

	public bool Reconnect()
	{
		string url = _socket.GetRequestedUrl();
		if (_socket.GetReadyState() != WebSocketPeer.State.Closed)
		{
			_socket.Close();
		}
		_prevState = WebSocketPeer.State.Closed;
		return Connect(url);
		
	}

	public void QueuePacketData(IPacketData data)
	{
		_sendQueue.Enqueue(data);
	}

	public void SendPacket(PacketContainer packet)
	{
		if (_socket.GetReadyState() != WebSocketPeer.State.Open)
		{
			Global.Logger.Log(LogLevel.Error, "Can't send packet: Socket not open");
			return;
		}
		string json = JsonSerializer.Serialize(packet, _options);
		_socket.SendText(json);
	}

	private void SendAllPacketData()
	{
		if (_sendQueue.Count == 0) return;
		var pc = new PacketContainer
		{
			Origin = "client",
			Data = _sendQueue.ToList(),
		};
		_sendQueue.Clear();
		SendPacket(pc);
	}

	public override void _Process(double delta)
	{
		_socket.Poll();
		WebSocketPeer.State state = _socket.GetReadyState();

		// on state transitions
		if (state != _prevState)
		{
			switch (state)
			{
				case WebSocketPeer.State.Connecting:
					GD.Print("WebSocket: connecting...");
					break;
				case WebSocketPeer.State.Open:
					GD.Print("WebSocket: connected");
					break;
				case WebSocketPeer.State.Closing:
					GD.Print("WebSocket: closing...");
					break;
				case WebSocketPeer.State.Closed:
					SetProcess(false);
					int code = _socket.GetCloseCode();
					GD.Print($"WebSocket: closed with code {code}. Clean: {code != -1}");
					break;
			}
			_prevState = state;
		}

		// every tick
		switch (state)
		{
			case WebSocketPeer.State.Open:
				while (_socket.GetAvailablePacketCount() > 0)
				{
					byte[] packet = _socket.GetPacket();
					if (!_socket.WasStringPacket()) continue;
					string packetText = packet.GetStringFromUtf8();
					try
					{
						var packetObj = JsonSerializer.Deserialize<PacketContainer>(packetText, _options);
						if (packetObj != null)
						{
							ReceiveQueue.Enqueue(packetObj);
						}
						else
						{
							GD.PushWarning($"WebSocket: null from packet {packetText}");
						}
					}
					catch (JsonException e)
					{
						GD.PushError($"WebSocket: failed to deserialize: {e.Message}");
					}
				}

				SendAllPacketData();

				break;
			case WebSocketPeer.State.Connecting:
			case WebSocketPeer.State.Closing:
			case WebSocketPeer.State.Closed:
				break;
			default:
				GD.PushError("WebSocket: unknown state");
				break;
		}
	}
}
