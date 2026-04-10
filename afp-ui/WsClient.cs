using System.Collections.Generic;
using System.Text.Json;
using AFP.Packet;
using Godot;

namespace AFP;

public partial class WsClient : Node
{
	public static WsClient Instance { get; private set; }

	public Queue<PacketContainer> PacketQueue { get; private set; }

	private WebSocketPeer _socket;

	private readonly JsonSerializerOptions _options = new JsonSerializerOptions
	{
		PropertyNameCaseInsensitive = true,
		PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
	};

	public override void _Ready()
	{
		Instance = this;
		_socket = new WebSocketPeer();
		PacketQueue = new Queue<PacketContainer>();
		SetProcess(false);
	}

	public bool Connect(string url)
	{
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

	public void SendPacket(PacketContainer packet)
	{
		string json = JsonSerializer.Serialize(packet, _options);
		_socket.SendText(json);
	}

	public override void _Process(double delta)
	{
		_socket.Poll();

		WebSocketPeer.State state = _socket.GetReadyState();

		switch (state)
		{
			case WebSocketPeer.State.Connecting:
				GD.Print("WebSocket: still trying to connect");
				break;
			case WebSocketPeer.State.Open:
				while (_socket.GetAvailablePacketCount() > 0)
				{
					byte[] packet = _socket.GetPacket();
					if (_socket.WasStringPacket())
					{
						string packetText = packet.GetStringFromUtf8();
						var packetObj = JsonSerializer.Deserialize<PacketContainer>(packetText, _options);
						PacketQueue.Enqueue(packetObj);
					}
				}

				break;
			case WebSocketPeer.State.Closing:
				GD.Print("WebSocket: closing...");
				break;
			case WebSocketPeer.State.Closed:
				int code = _socket.GetCloseCode();
				GD.Print($"WebSocket: closed with code {code}. Clean: {code != -1}");
				SetProcess(false);
				break;
			default:
				GD.PushError("WebSocket: unknown state");
				break;
		}
	}
}
