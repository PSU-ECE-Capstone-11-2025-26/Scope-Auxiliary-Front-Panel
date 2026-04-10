namespace AFP.Packet.Data;

public class ScopeInfoPacketData : IPacketData
{
	public required ushort ChannelCount { get; set; }
}
