all:
	$(CC) -Wall -O2 -g -o simpleio main.c
	$(CC) -Wall -O2 -g -o udp-send udp-send.c
	$(CC) -Wall -O2 -g -o gethostname gethostname.c

install:
	install -D --target $(PREFIX)/bin simpleio udp-send gethostname
