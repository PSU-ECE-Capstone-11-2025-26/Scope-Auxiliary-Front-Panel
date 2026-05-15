using System.Text.Json.Serialization;

namespace AFP.Packet.Data;

[JsonPolymorphic(TypeDiscriminatorPropertyName = "type")]
[JsonDerivedType(typeof(ScopeInfoPacketData), typeDiscriminator: "ScopeInfo")]
[JsonDerivedType(typeof(ScopeStatePacketData), typeDiscriminator: "ScopeState")]
[JsonDerivedType(typeof(ScopeListPacketData), typeDiscriminator: "ScopeList")]
[JsonDerivedType(typeof(MacroActionPacketData), typeDiscriminator: "MacroRecord")]
[JsonDerivedType(typeof(MacroStatePacketData), typeDiscriminator: "MacroState")]
[JsonDerivedType(typeof(ScopeActionPacketData), typeDiscriminator: "ScopeAction")]
[JsonDerivedType(typeof(LogMessagePacketData), typeDiscriminator: "LogMessage")]
[JsonDerivedType(typeof(ErrorPacketData), typeDiscriminator: "Error")]
[JsonDerivedType(typeof(HandshakePacketData), typeDiscriminator: "Handshake")]
public interface IPacketData {}
