class QuestionGenerator:

    def generate_initial(
        self,
        competency: str,
    ) -> str:

        questions = {
            "technical_skills":
                "Tell me about the main technologies you have used in backend development.",

            "problem_solving":
                "Tell me about a difficult technical problem you faced and how you solved it.",

            "system_design":
                "Describe a backend system you designed and explain the major architectural decisions.",

            "software_engineering":
                "How do you ensure the software you build remains maintainable and reliable?",

            "databases":
                "Tell me about a database problem you encountered and how you handled it.",

            "cloud_devops":
                "Describe your experience deploying and operating backend systems.",

            "communication":
                "Tell me about a time you had to explain a technical decision to others.",

            "leadership":
                "Tell me about a time you led, mentored, or coordinated other people.",

            "adaptability":
                "Tell me about a time you had to learn something new to complete a project.",

            "project_experience":
                "Walk me through a project you built and the role you played in it.",
        }

        return questions.get(
            competency,
            f"Tell me about your experience with {competency}.",
        )

    def generate_follow_up(
        self,
        competency: str,
        answer: str,
    ) -> str:

        return (
            f"You mentioned an important point about "
            f"{competency}. Can you explain that in more "
            f"detail and describe the specific decisions "
            f"you made?"
        )

    def generate_pivot(
        self,
        competency: str,
    ) -> str:

        return (
            f"You mentioned experience related to "
            f"{competency}. I'd like to explore that. "
            f"Can you describe a concrete example?"
        )

    def generate_recovery(
        self,
        competency: str,
    ) -> str:

        from app.stages.stage4_interview.questions.question_generator import (
            generate_recovery_question,
        )

        return generate_recovery_question(competency)