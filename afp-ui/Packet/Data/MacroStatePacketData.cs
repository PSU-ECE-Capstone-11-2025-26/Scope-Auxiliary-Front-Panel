namespace AFP.Packet.Data;

public class MacroStatePacketData : IPacketData
{
	public required bool[] Macros { get; set; }
}
