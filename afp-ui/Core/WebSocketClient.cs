using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using AFP.Packet;
using AFP.Packet.Data;
using Godot;

namespace AFP.Core;

public partial class WebSocketClient : Node
{
	[Signal]
	public delegate void ConnectedEventHandler();
	
	public static WebSocketClient Instance { get; private set; }

	public Queue<PacketContainer> ReceiveQueue { get; private set; }
	private readonly Queue<IPacketData> _sendQueue = new();

	private WebSocketPeer _socket;
	private WebSocketPeer.State _prevState = WebSocketPeer.State.Closed;
	private double _connectionAttemptTime;
	private const double ConnectionAttemptTime = 1.5;
	private ushort _connectionAttempts;
	private const ushort ConnectionAttemptsMax = 5;

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
		_connectionAttemptTime = 0;
		_socket = new WebSocketPeer();
		Error err = _socket.ConnectToUrl(url);
		if (err == Error.Ok)
		{
			Global.Logger.Log(LogLevel.Debug, $"WebSocket: connecting to {url}...");
			SetProcess(true);
			return true;
		}
		else
		{
			Global.Logger.Log(LogLevel.Debug, "WebSocket: couldn't connect (params or peer invalid?)", true);
			SetProcess(false);
			return false;
		}
	}

	public bool Reconnect()
	{
		Global.Logger.Log(LogLevel.Debug, $"Socket reconnecting, try {_connectionAttempts}");
		string url = _socket.GetRequestedUrl();
		Close();
		return Connect(url);
	}

	private void Close()
	{
		if (_socket.GetReadyState() != WebSocketPeer.State.Closed)
		{
			_socket.Close();
		}
		SetProcess(false);
		_prevState = WebSocketPeer.State.Closed;
	}

	public void QueuePacketData(IPacketData data)
	{
		_sendQueue.Enqueue(data);
	}

	private void SendPacket(PacketContainer packet)
	{
		if (_socket.GetReadyState() != WebSocketPeer.State.Open)
		{
			Global.Logger.Log(LogLevel.Error, "WebSocket: error sending; socket not open");
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
					Global.Logger.Log(LogLevel.Debug, "WebSocket: connected");
					_connectionAttemptTime = 0;
					_connectionAttempts = 0;
					EmitSignal(SignalName.Connected);
					QueuePacketData(new HandshakePacketData
					{
						Id = ProjectSettings.GetSetting("application/config/name").ToString(),
						Version = ProjectSettings.GetSetting("application/config/version").ToString(),
					});
					break;
				case WebSocketPeer.State.Closing:
					GD.Print("WebSocket: closing...");
					break;
				case WebSocketPeer.State.Closed:
					SetProcess(false);
					int code = _socket.GetCloseCode();
					GD.Print($"WebSocket: closed with code {code}. Clean: {code != -1}");
					if (code == -1)
					{
						Reconnect();
					}
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
			case WebSocketPeer.State.Closed:
			case WebSocketPeer.State.Connecting:
				_connectionAttemptTime += delta;
				if (_connectionAttemptTime > ConnectionAttemptTime)
				{
					_connectionAttempts++;
					
					if (_connectionAttempts > ConnectionAttemptsMax)
					{
						Close();
						Global.Logger.Log(LogLevel.Error, "Can't connect to socket: please reboot", true);
						return;
					}
					Reconnect();
				}
				break;
			case WebSocketPeer.State.Closing:
				break;
			default:
				GD.PushError("WebSocket: unknown state");
				break;
		}
	}
}
