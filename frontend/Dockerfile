FROM node:20-alpine

WORKDIR /srv/sentinel-ui

COPY package.json package-lock.json* ./
RUN npm install

COPY . .

# Baked into the static build — override for non-localhost deployments
ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

EXPOSE 5173
CMD ["npm", "run", "preview"]
