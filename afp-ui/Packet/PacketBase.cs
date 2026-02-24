using System.Text.Json.Serialization;

namespace AFP.Packet;

public enum PacketType
{
    Ack = 0,
    Nack = 1,
    Request = 2,
    ScopeConfig = 3,
    ScopeState = 4,
    Macro = 5,
}

public class PacketBase
{
    public PacketType Type { get; set; }
}