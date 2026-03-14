<?php

declare(strict_types=1);

class Greeter
{
    private string $name;

    public function __construct(string $name)
    {
        $this->name = $name;
    }

    public function greet(): string
    {
        return 'Hello, ' . $this->name . '!';
    }

    public function farewell(): string
    {
        return 'Goodbye, ' . $this->name . '!';
    }
}

$greeter = new Greeter('World');
echo $greeter->greet();
