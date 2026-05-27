import logging

from tekafp.afp import TekAfp


logger = logging.getLogger(__name__)


def main() -> None:
    afp = TekAfp()
    afp.setup()
    afp.run()
    logger.info("Goodbye!")


if __name__ == "__main__":
    main()
