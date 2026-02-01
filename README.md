# archetype3
This is a new revamped version of the project  https://github.com/kcl-ddh/digipal


**PLEASE READ [CONTRIBUTING.MD](./CONTRIBUTING.md) BEFORE CONTRIBUTING**

## Structure
The app is divided into a backend services repo, and a frontend repo.
This repo is concerned with the backend/ APIs with all the services it depends on.

### Services
This project uses:
- Search Engine: meilisearch
- Database: Postgres
- IIIF Image Server: [SIPI](https://github.com/dasch-swiss/sipi)

### Backend/ API
The backend API is a Django/ Django Rest Framework app written in Python3.  
It uses Poetry as a package manager.  
The API documentation is hosted on the url `/api/v1/docs`

## local development
There is a compose.yaml configuration file already set with all required services.
you can use compose simply with:  
```
>>> docker compose up
```

Alternatively, you can set up your own environment as you wish using poetry, 
and the list of services specificed earlier.

### enviornment variables
You will also need to specify the environment variables for your setup.  
You need to store them in a file `config/.env`. For a start, you can copy
the values from `config/test.env`

## Deployment
The backend is released as a docker image using the github packages services:  
https://github.com/archetype-pal/archetype3/pkgs/container/archetype3

If you don't have specific requirements for deployment, the compose configuration is
a good way to start deploying the system.
Just copy the file on your server, while following the comments in the file that start with `production:`


### Running a docker compose instance
If you want to use docker compose, you can use the Makefile aliases to make your live easier.

First time you run your server, you will need to apply the migrations to your database
```
>>> make migrate
```

but first make sure to have a server running in the background 
```
>>> make up-bg
```
