import time
import pyvisa

def connect_scope():
    rm = pyvisa.ResourceManager("@py")

    while True:
        resources = rm.list_resources()
        usb = [r for r in resources if r.startswith("USB")]
        if usb:
            scope = rm.open_resource(usb[0])
            scope.timeout = 5000
            scope.write_termination = "\n"
            scope.read_termination = "\n"
            return scope
        print("No USB scope found, retrying in 2s...")
        time.sleep(2)

def main():
    scope = connect_scope()
    idn = scope.query("*IDN?").strip()
    print("Connected:", idn)

    print("CH1 pos was:", scope.query("CH1:POSition?").strip())
    scope.write("CH1:POSition -2.0")
    print("CH1 pos is:", scope.query("CH1:POSition?").strip())

    scope.close()

if __name__ == "__main__":
    main()
