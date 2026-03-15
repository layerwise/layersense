from manim import (
    BLUE,
    BLUE_E,
    GREEN,
    LEFT,
    RIGHT,
    UP,
    YELLOW,
    Circle,
    Create,
    Dot,
    FadeIn,
    Scene,
    Square,
    Text,
    Transform,
    Write,
)


class ExampleScene(Scene):
    def construct(self):
        # A blue circle with a light fill
        circle = Circle(radius=1, color=BLUE).set_fill(BLUE_E, opacity=0.4)

        # A green square positioned to the right
        square = Square(side_length=1.6, color=GREEN).shift(RIGHT * 2)

        # A title text above the circle
        title = Text("Manim Community Scene", font_size=40).next_to(circle, UP)

        # Animate basic creation and transitions
        self.play(Create(circle))
        self.play(FadeIn(square))
        self.play(circle.animate.shift(LEFT * 1.5))
        self.play(Transform(circle, square))
        self.play(Write(title))
        dot = Dot(point=circle.get_left(), color=YELLOW)
        self.play(FadeIn(dot))
        self.play(dot.animate.move_to(circle.get_right()))

        self.wait(1)
