namespace AFP.Packet;

public class MacroStatePacketData : IPacketData
{
	public required bool[] Macros { get; set; }
}
