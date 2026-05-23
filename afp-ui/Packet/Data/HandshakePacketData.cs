namespace AFP.Packet.Data;

public class HandshakePacketData : IPacketData
{
	public required string Id { get; set; }
	public required string Version { get; set; }
}
