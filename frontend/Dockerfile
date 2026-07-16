# syntax=docker/dockerfile:1.6

# ---------- Estagio 1: build da SPA com Node + Vite ----------
FROM node:20-alpine AS build

WORKDIR /app

# Copia manifests primeiro para aproveitar cache de camadas
COPY package.json package-lock.json ./

# `npm ci` e deterministico — exige package-lock.json presente
RUN npm ci

# Copia o resto do codigo-fonte
COPY . .

# Builda: `tsc -b && vite build` -> produz /app/dist
RUN npm run build

# ---------- Estagio 2: serve com nginx ----------
FROM nginx:alpine AS serve

# Remove a config default do nginx para nao conflitar
RUN rm /etc/nginx/conf.d/default.conf

# Copia nossa config customizada (SPA routing + cache)
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copia somente o dist/ do estagio build (sem node_modules, sem fonte)
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

# Comando padrao do nginx:alpine (mantido explicito para clareza)
CMD ["nginx", "-g", "daemon off;"]
