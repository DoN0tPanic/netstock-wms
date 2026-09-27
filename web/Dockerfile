FROM node:22.23.3-alpine3.24 AS build
RUN apk add --no-cache git
WORKDIR /app
# `npm ci` installa esattamente il lockfile, e si ferma se non corrisponde a
# package.json; `npm install` poteva risolvere versioni diverse da quelle provate.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# Il commit dell'interfaccia, per la pagina Impostazioni: se un browser tiene
# aperta la versione di prima di un aggiornamento, lo si vede (vedi api/Dockerfile).
RUN --mount=type=bind,from=git,target=/tmp/git \
    export VITE_COMMIT="$(git -c safe.directory='*' --git-dir=/tmp/git log -1 --format=%h 2>/dev/null)" \
           VITE_DATA_COMMIT="$(git -c safe.directory='*' --git-dir=/tmp/git log -1 --format=%cI 2>/dev/null)" \
           VITE_COSTRUITA="$(date -u +%Y-%m-%dT%H:%M:%SZ)" && \
    npm run build

# Ramo stabile di nginx (anni pari): il ramo 1.27 non riceveva più correzioni.
FROM nginx:1.30.5-alpine3.24
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
