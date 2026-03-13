namespace AFP.Packet;

public class MacroRecordPacketData : IPacketData
{
	public required bool Record { get; set; }
	public required ushort Slot { get; set; }
}
