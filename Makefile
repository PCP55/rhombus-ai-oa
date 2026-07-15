.PHONY: build start cleanup

build:
	docker compose up --build

start:
	docker compose up

cleanup:
	docker system prune -a --volumes

stop:
	docker stop $(docker ps -q)

list:
	docker ps
