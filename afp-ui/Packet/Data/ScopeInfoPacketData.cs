namespace AFP.Packet;

public class ScopeInfoPacketData : IPacketData
{
	public required ushort ChannelCount { get; set; }
}