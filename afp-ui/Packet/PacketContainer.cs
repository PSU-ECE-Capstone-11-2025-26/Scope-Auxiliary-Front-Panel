using System.Collections.Generic;
using AFP.Packet.Data;

namespace AFP.Packet;

public class PacketContainer
{
	public required string Origin { get; set; }
	public required List<IPacketData> Data { get; set; }
}
