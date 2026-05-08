namespace AFP.Packet.Data;

public class LogMessagePacketData : IPacketData
{
	public required ushort Level { get; set; }
	public required string Message { get; set; }
	public required bool Toast { get; set; }
}
