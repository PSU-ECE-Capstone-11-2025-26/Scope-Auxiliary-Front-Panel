namespace AFP.Packet.Data;

public class ScopeInfoPacketData : ScopePacketData
{
	public required string Idn { get; set; }
	public required ushort ChannelCount { get; set; }
}
