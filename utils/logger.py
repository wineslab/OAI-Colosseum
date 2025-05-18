import logging


def set_logger(filename: str) -> None:
    # configure logger and console output
    logging.basicConfig(level=logging.DEBUG, filename='/logs/{}'.format(filename), filemode='a+',
        format='%(asctime)-15s %(levelname)-8s %(message)s')
    formatter = logging.Formatter('%(asctime)-15s %(levelname)-8s %(message)s')
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    logging.getLogger('').addHandler(console)
