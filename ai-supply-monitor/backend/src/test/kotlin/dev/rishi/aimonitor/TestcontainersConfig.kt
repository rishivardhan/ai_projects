package dev.rishi.aimonitor

import org.springframework.boot.test.context.TestConfiguration
import org.springframework.boot.testcontainers.service.connection.ServiceConnection
import org.springframework.context.annotation.Bean
import org.testcontainers.containers.PostgreSQLContainer
import org.testcontainers.utility.DockerImageName

@TestConfiguration(proxyBeanMethods = false)
class TestcontainersConfig {
    @Bean
    @ServiceConnection
    fun postgres(): PostgreSQLContainer<*> =
        PostgreSQLContainer(DockerImageName.parse(TIMESCALE_IMAGE).asCompatibleSubstituteFor("postgres"))

    companion object {
        const val TIMESCALE_IMAGE = "timescale/timescaledb:2.30.2-pg16"
    }
}
