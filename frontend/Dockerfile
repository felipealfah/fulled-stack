# syntax=docker/dockerfile:1.6

# ---------- Estagio 1: build da SPA com Node + Vite ----------
FROM node:20-alpine AS build

WORKDIR /app

# Copia manifests primeiro para aproveitar cache de camadas
COPY package.json package-lock.json ./

# `npm ci` e deterministico — exige package-lock.json presente
RUN npm ci

# Build args para variáveis Vite (injetadas em build-time, não em runtime)
ARG VITE_API_URL
ARG VITE_LOWTICKET_SUPABASE_URL
ARG VITE_LOWTICKET_SUPABASE_PB_KEY
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_LOWTICKET_SUPABASE_URL=$VITE_LOWTICKET_SUPABASE_URL
ENV VITE_LOWTICKET_SUPABASE_PB_KEY=$VITE_LOWTICKET_SUPABASE_PB_KEY

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
