package dev.rishi.aimonitor

import org.springframework.boot.autoconfigure.SpringBootApplication
import org.springframework.boot.context.properties.ConfigurationPropertiesScan
import org.springframework.boot.runApplication
import org.springframework.modulith.Modulithic
import org.springframework.scheduling.annotation.EnableAsync
import org.springframework.scheduling.annotation.EnableScheduling

@Modulithic(systemName = "AI Supply-Chain Market Monitor")
@SpringBootApplication
@ConfigurationPropertiesScan
@EnableScheduling
@EnableAsync
class AiMonitorApplication

fun main(args: Array<String>) {
    runApplication<AiMonitorApplication>(*args)
}
