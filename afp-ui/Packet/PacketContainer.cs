using System.Collections.Generic;

namespace AFP.Packet;

public class PacketContainer
{
	public required string From { get; set; }
	public required List<IPacketData> Data { get; set; }
}
