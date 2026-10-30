package dev.rishi.aimonitor

import org.junit.jupiter.api.Test
import org.springframework.modulith.core.ApplicationModules
import org.springframework.modulith.docs.Documenter

class ModularityTests {
    private val modules = ApplicationModules.of(AiMonitorApplication::class.java)

    /** Fails the build on any illegal cross-module dependency or cycle. */
    @Test
    fun `module boundaries hold`() {
        modules.verify()
    }

    @Test
    fun `write module documentation`() {
        Documenter(modules).writeDocumentation()
    }
}
