# Plans the root offline against a mocked Google provider to check the session
# flag rules. Run by infra/tests/validate-terraform.sh; needs no credentials.

mock_provider "google" {
  mock_data "google_project" {
    defaults = {
      number = "000000000000"
    }
  }
}

run "inference_cpu_requires_lab" {
  command = plan

  variables {
    lab_enabled           = false
    inference_cpu_enabled = true
  }

  expect_failures = [var.inference_cpu_enabled]
}

run "inference_cpu_session_plans" {
  command = plan

  variables {
    lab_enabled           = true
    inference_cpu_enabled = true
  }

  assert {
    condition     = length(module.gke[0].inference_cpu_pool_names) == 1
    error_message = "The inference CPU pool must be planned when inference_cpu_enabled is true."
  }
}
