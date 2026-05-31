namespace AFP.Packet.Data;

public class ScopeInfoPacketData : ScopePacketData
{
	public required bool Connected { get; set; }
	public required bool Synced { get; set; }
	public required string Idn { get; set; }
	public required ushort ChannelCount { get; set; }
}
