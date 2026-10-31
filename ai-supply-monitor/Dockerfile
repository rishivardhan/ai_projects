# One image: the Spring Boot fat jar serves the API and the built frontend.
FROM node:22.20.0-alpine AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM gradle:8.14.3-jdk21 AS backend
WORKDIR /src
COPY backend/ ./
COPY --from=frontend /src/dist/ src/main/resources/static/
RUN ./gradlew --no-daemon bootJar -x test

FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=backend /src/build/libs/*.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75", "-jar", "app.jar"]
