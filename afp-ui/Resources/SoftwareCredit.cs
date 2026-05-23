using Godot;

namespace AFP.Resources;

[GlobalClass]
public partial class SoftwareCredit : Resource
{
	[Export] public string SoftwareName { get; private set; }
	[Export(PropertyHint.File)] public string LicenseFile { get; private set; }
}
