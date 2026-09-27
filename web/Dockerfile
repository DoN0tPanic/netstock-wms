FROM node:22.23.3-alpine3.24 AS build
WORKDIR /app
# `npm ci` installa esattamente il lockfile, e si ferma se non corrisponde a
# package.json; `npm install` poteva risolvere versioni diverse da quelle provate.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# Ramo stabile di nginx (anni pari): il ramo 1.27 non riceveva più correzioni.
FROM nginx:1.30.5-alpine3.24
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
